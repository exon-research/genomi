from __future__ import annotations

import json
from typing import Any
from unittest import mock

from genomi.interfaces.mcp import handle_request
from genomi.lab.provider_policy import SourceFamily
from genomi.lab.service import GenomiLabService
from genomi.lab.store import GenomiLabStore
from genomi.interfaces.presentation import present_result
from genomi.operations import call_operation

from tests.genomilab_e2e_support import GenomiLabEndToEndCase, PATIENT_A_VCF
from tests.genomilab_support import TEST_LAB_KEY_PROVIDER


class GenomiLabAgentMultiturnTests(GenomiLabEndToEndCase):
    """Prove the native host can own a complete, revisable investigation."""

    def _new_service(self, session_id: str) -> GenomiLabService:
        service = GenomiLabService(
            store=GenomiLabStore(
                self.store_path, key_provider=TEST_LAB_KEY_PROVIDER
            ),
            session_id=session_id,
            operation_call=call_operation,
            agent_host_id="mcp-codex-test",
            agent_processing_destination=(
                "current MCP host (Codex test; host-reported identity)"
            ),
        )
        service.configure_evidence_gateway(
            fixtures={SourceFamily.LITERATURE: self._public_evidence_fixture()}
        )
        self.services.append(service)
        return service

    @staticmethod
    def _approval(candidate: dict[str, Any]) -> dict[str, Any]:
        return {
            key: value
            for key, value in candidate.items()
            if key
            not in {
                "status",
                "requires_explicit_approval",
                "user_id",
                "investigation_id",
            }
        } | {"approved": True}

    def _authorize(
        self, investigation_id: str, *, observation_revision_ids: list[str] | None = None
    ) -> dict[str, Any]:
        self.service.form_agent_specialist_board(
            investigation_id,
            specialists=[
                {
                    "specialist_id": "specialist-genome-evidence",
                    "role": "Genome evidence specialist",
                    "task": "Review approved genome evidence through the main agent",
                },
                {
                    "specialist_id": "specialist-public-evidence",
                    "role": "Public evidence specialist",
                    "task": "Review relevant public evidence",
                },
            ],
        )
        prepared = self.service.prepare_agent_authorization(
            investigation_id,
            observation_revision_ids=observation_revision_ids,
            purpose="Investigate the synthetic condition with the approved patient context",
        )
        candidate = prepared["candidate"]
        result = self.service.authorize_investigation_context(
            investigation_id, self._approval(candidate)
        )
        self.assertEqual(result["status"], "awaiting_agent_plan")
        self.assertEqual(
            result["authorization"]["authorization_scope"]["agent_session"][
                "recipient_id"
            ],
            "mcp-codex-test",
        )
        return result

    def _submit_catalog_requests(
        self,
        investigation_id: str,
        capabilities: list[str],
        *,
        overrides: dict[str, dict[str, Any]] | None = None,
    ) -> dict[str, dict[str, Any]]:
        catalog = self.service.investigation_capability_catalog(investigation_id)
        requests: list[dict[str, Any]] = []
        for index, capability in enumerate(capabilities, start=1):
            entry = catalog[capability]
            parameters = (overrides or {}).get(capability)
            if parameters is None:
                templates = entry.get("exact_request_templates") or []
                parameters = (
                    dict(templates[0])
                    if templates
                    else dict(entry.get("parameters") or {})
                )
            requests.append(
                {
                    "id": f"request-{index}-{capability}",
                    "capability": capability,
                    "parameters": parameters,
                }
            )
        accepted = self.service.submit_agent_plan(
            investigation_id,
            focus_question=(
                "Which findings and gaps follow from " + ", ".join(capabilities) + "?"
            ),
            specialist_assignments=[
                {
                    "specialist_id": "specialist-genome-evidence",
                    "task": "Review the approved genome and profile evidence for this round",
                },
                {
                    "specialist_id": "specialist-public-evidence",
                    "task": "Review the relevant public evidence for this round",
                },
            ],
            requests=requests,
        )
        self.assertEqual(accepted["status"], "accepted")
        results: dict[str, dict[str, Any]] = {}
        for request in requests:
            result = self.service.execute_agent_request(
                investigation_id, str(request["id"])
            )
            self.assertEqual(result["status"], "completed", result)
            results[str(request["capability"])] = result["result"]
        round_id = str(accepted["investigation_round"]["round_id"])
        investigation = self.service.investigation(investigation_id)
        snapshot = self.service.store.get_profile_snapshot(
            str(investigation["patient_molecular_snapshot_id"])
        )
        profile_revision_ids = list(snapshot["observation_revision_ids"])
        report = {
            "findings": [
                {
                    "statement": "The approved patient context was reviewed for this investigation round.",
                    "stance": "context_only",
                    "evidence_record_ids": [],
                    "profile_revision_ids": profile_revision_ids[:1],
                }
            ],
            "gaps": [],
        }
        for specialist_id in (
            "specialist-genome-evidence",
            "specialist-public-evidence",
        ):
            self.service.record_agent_specialist_report(
                investigation_id,
                round_id=round_id,
                specialist_id=specialist_id,
                report=report,
            )
        return results

    def _mcp_call(
        self, operation: str, arguments: dict[str, object]
    ) -> dict[str, Any]:
        runtime = mock.Mock()
        runtime.service = self.service
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
        self.assertIsNot(response["result"].get("isError"), True, response)
        return json.loads(response["result"]["content"][0]["text"])

    def _brief_from_published_inspection(
        self, investigation_id: str
    ) -> dict[str, Any]:
        published = self._mcp_call(
            "genomilab.inspect_investigation",
            {"investigation_id": investigation_id},
        )
        investigation = published["investigation"]
        schema = published["brief_authoring"]["brief_schema"]
        properties = schema["properties"]
        hypotheses = {
            item["hypothesis_id"]: item
            for item in investigation["current_hypotheses"]
        }
        hypothesis_ids = list(
            properties["hypothesis_ids"]["items"].get("enum", [])
        )
        gap_ids = list(properties["gap_ids"]["items"].get("enum", []))
        claims: list[dict[str, Any]] = []
        for hypothesis_id in hypothesis_ids:
            hypothesis = hypotheses[hypothesis_id]
            claims.append(
                {
                    "statement": hypothesis["statement"],
                    "claim_role": (
                        "counterevidence"
                        if hypothesis["kind"] == "counterevidence"
                        else "candidate_hypothesis"
                    ),
                    "evidence_record_ids": hypothesis["evidence_record_ids"],
                    "profile_revision_ids": hypothesis["profile_revision_ids"],
                }
            )
        for gap_id in gap_ids:
            gap = hypotheses[gap_id]
            claims.append(
                {
                    "statement": gap["statement"],
                    "claim_role": "limitation",
                    "evidence_record_ids": gap["evidence_record_ids"],
                    "profile_revision_ids": gap["profile_revision_ids"],
                }
            )
        confirmation_schema = properties["confirmation_needs"]
        confirmation_needs = (
            [confirmation_schema["items"]["enum"][0]]
            if confirmation_schema.get("minItems")
            else []
        )
        case_term = self._case_term(
            published["brief_authoring"]["case_narrative_contract"],
            profile_revision_ids=list(
                dict.fromkeys(
                    revision_id
                    for claim in claims
                    for revision_id in claim["profile_revision_ids"]
                )
            ),
            evidence_record_ids=list(
                dict.fromkeys(
                    evidence_id
                    for claim in claims
                    for evidence_id in claim["evidence_record_ids"]
                )
            ),
        )
        summary = (
            claims[0]["statement"]
            if claims
            else f"Patient observation: The profile records {case_term} as a research observation."
        )
        return {
            "title": published["brief_authoring"]["brief_title_fallback"],
            "summary": summary,
            "clinical_stage": properties["clinical_stage"]["enum"][0],
            "timeline": [],
            "claims": claims,
            "hypothesis_ids": hypothesis_ids,
            "gap_ids": gap_ids,
            "confirmation_needs": confirmation_needs,
            "clinician_questions": [],
            "clinical_boundary": properties["clinical_boundary"]["enum"][0],
            "change_summary": f"Prepared a traceable {case_term} research brief.",
        }

    @staticmethod
    def _case_term(
        contract_owner: dict[str, Any],
        *,
        profile_revision_ids: list[str] | None = None,
        evidence_record_ids: list[str] | None = None,
    ) -> str:
        anchors = contract_owner["anchors"]
        selected_profile_ids = set(profile_revision_ids or [])
        selected_evidence_ids = set(evidence_record_ids or [])
        if selected_profile_ids or selected_evidence_ids:
            anchors = [
                anchor
                for anchor in anchors
                if (
                    anchor.get("profile_revision_id") in selected_profile_ids
                    or anchor.get("evidence_record_id") in selected_evidence_ids
                )
            ]
        return max(
            (str(anchor["text"]) for anchor in anchors),
            key=lambda value: (" in " in value, len(value)),
        )

    def _run_evidence_and_synthesis(
        self,
        investigation_id: str,
        *,
        supersedes_hypothesis_id: str | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        catalog = self.service.investigation_capability_catalog(investigation_id)
        evidence_capabilities = [
            "investigation.project_profile",
            "genomi.variant.resolve",
            "public_evidence.retrieve",
        ]
        self.assertTrue(all(catalog[item]["available"] for item in evidence_capabilities))
        self._submit_catalog_requests(investigation_id, evidence_capabilities)

        presented = present_result(
            "genomilab.inspect_investigation",
            self.service.inspect_agent_investigation(investigation_id),
        )
        presented_catalog = presented["capability_catalog"]
        relation_parameters = dict(
            presented_catalog["investigation.register_disease_relation"][
                "exact_request_templates"
            ][0]
        )
        relation = self._submit_catalog_requests(
            investigation_id,
            ["investigation.register_disease_relation"],
            overrides={
                "investigation.register_disease_relation": relation_parameters
            },
        )["investigation.register_disease_relation"]["disease_relation"]
        self.assertEqual(relation["operation"], "investigation.register_disease_relation")

        synthesis_view = present_result(
            "genomilab.inspect_investigation",
            self.service.inspect_agent_investigation(investigation_id),
        )
        synthesis_catalog = synthesis_view["capability_catalog"]
        hypothesis_entry = synthesis_catalog["investigation.register_hypothesis"]
        hypothesis_parameters = dict(hypothesis_entry["anchored_request_cases"][0])
        case_term = self._case_term(
            hypothesis_entry["request_contract"]["fields"]["statement"],
            profile_revision_ids=hypothesis_parameters["profile_revision_ids"],
            evidence_record_ids=hypothesis_parameters["evidence_record_ids"],
        )
        hypothesis_parameters["statement"] = (
            f"Model inference: The finding {case_term} may contribute to the "
            "reported condition, but this remains only a candidate hypothesis; "
            "causality, mechanism, and clinical significance are unestablished."
        )
        if supersedes_hypothesis_id is not None:
            hypothesis_parameters["supersedes_hypothesis_id"] = (
                supersedes_hypothesis_id
            )
        synthesis = self._submit_catalog_requests(
            investigation_id,
            ["investigation.register_hypothesis", "investigation.register_gap"],
            overrides={
                "investigation.register_hypothesis": hypothesis_parameters,
                "investigation.register_gap": {
                    **dict(
                        synthesis_catalog["investigation.register_gap"][
                            "anchored_request_cases"
                        ][0]
                    ),
                    "statement": (
                        "Evidence gap: Independent clinical confirmation for "
                        f"{case_term} remains an open requirement."
                    ),
                },
            },
        )
        return (
            synthesis["investigation.register_hypothesis"]["hypothesis"],
            synthesis["investigation.register_gap"]["hypothesis"],
        )

    def test_native_agent_flow_revises_hypothesis_after_new_patient_information(
        self,
    ) -> None:
        parsed, _ = self._intake_current_user(
            PATIENT_A_VCF,
            nickname="Synthetic native-host patient",
            source_name="native-host-patient.vcf",
        )
        workspace = self.service.open_agent_workspace()
        self.assertEqual(workspace["status"], "ready")
        self.assertEqual(workspace["execution"]["owner"], "underlying_agent")
        research_tools = self.service.list_agent_research_tools()
        by_provider = {
            item["provider"]: item
            for item in research_tools["research_tools"]["integrations"]
        }
        self.assertEqual(set(by_provider), {"paperclip", "biohub-esm", "proto"})
        self.assertEqual(
            research_tools["usage_boundary"]["paperclip"],
            "approved_search_and_lookup_when_advertised",
        )
        for provider in ("biohub-esm", "proto"):
            self.assertEqual(by_provider[provider]["investigation_operations"], [])
            self.assertEqual(
                by_provider[provider]["policy_state"],
                "connection_only_no_product_operation",
            )

        self._add_molecular_profile(self.service)
        created = self.service.create_agent_investigation(
            {
                "question": "Could the molecular profile help investigate this condition?",
                "disease_scope": "Synthetic neuromuscular condition",
            }
        )
        investigation_id = str(created["investigation"]["investigation_id"])
        self._authorize(investigation_id)

        hypothesis_v1, gap_v1 = self._run_evidence_and_synthesis(investigation_id)
        wire_brief_v1 = self._brief_from_published_inspection(investigation_id)
        self.assertNotIn("modality_badges", wire_brief_v1)
        brief_v1 = self._mcp_call(
            "genomilab.submit_brief",
            {"investigation_id": investigation_id, "brief": wire_brief_v1},
        )["brief_version"]
        self.assertEqual(brief_v1["version"], 1)
        self.assertTrue(brief_v1["brief"]["modality_badges"])

        added = self.service.record_agent_patient_observations(
            investigation_id,
            [
                {
                    "modality": "phenotype",
                    "label": "Newly documented exercise intolerance",
                    "original_wording": "Exercise intolerance was newly documented",
                    "assertion_status": "present",
                    "verification_state": "user_confirmed",
                    "source_class": "patient_reported",
                }
            ],
        )
        refresh_candidate = added["authorization"]["candidate"]
        refreshed = self.service.authorize_investigation_context(
            investigation_id, self._approval(refresh_candidate)
        )
        self.assertEqual(refreshed["status"], "awaiting_agent_plan")
        self.assertEqual(refreshed["context"]["version"], 2)
        self.assertEqual(
            refreshed["context"]["agi_id"],
            parsed["active_genome_index"]["agi_id"],
        )

        hypothesis_v2, gap_v2 = self._run_evidence_and_synthesis(
            investigation_id,
            supersedes_hypothesis_id=str(hypothesis_v1["hypothesis_id"]),
        )
        self.assertEqual(hypothesis_v2["version"], 2)
        self.assertEqual(
            hypothesis_v2["logical_hypothesis_id"],
            hypothesis_v1["logical_hypothesis_id"],
        )
        self.assertEqual(
            hypothesis_v2["supersedes_hypothesis_id"],
            hypothesis_v1["hypothesis_id"],
        )

        wire_brief_v2 = self._brief_from_published_inspection(investigation_id)
        brief_v2 = self._mcp_call(
            "genomilab.submit_brief",
            {"investigation_id": investigation_id, "brief": wire_brief_v2},
        )["brief_version"]
        self.assertEqual(brief_v2["version"], 2)
        self.assertEqual(
            brief_v2["prior_brief_version_id"], brief_v1["brief_version_id"]
        )
        self.assertTrue(brief_v2["diff"]["patient_molecular_snapshot"]["changed"])

        final = self.service.inspect_agent_investigation(investigation_id)
        events = final["investigation"]["investigation_events"]
        self.assertIn("patient_information_recorded", {item["event_type"] for item in events})
        self.assertEqual(final["investigation"]["status"], "completed")
        self.assertEqual(len(final["investigation"]["brief_versions"]), 2)
        self.assertEqual(
            final["investigation"]["profile_snapshot_history"][0]["agi_id"],
            final["investigation"]["profile_snapshot_history"][1]["agi_id"],
        )

    def test_patient_provider_completion_returns_to_the_underlying_agent(self) -> None:
        self._intake_current_user(
            PATIENT_A_VCF,
            nickname="Synthetic provider-approval patient",
            source_name="provider-approval-patient.vcf",
        )
        self.assertEqual(self.service.open_agent_workspace()["status"], "ready")
        self._add_molecular_profile(self.service)
        created = self.service.create_agent_investigation(
            {
                "question": "What evidence could explain this condition?",
                "disease_scope": "Synthetic neuromuscular condition",
            }
        )
        investigation_id = str(created["investigation"]["investigation_id"])
        self._authorize(investigation_id)
        completed = {
            "status": "completed",
            "request_id": "request-paperclip",
            "capability": "public_evidence.retrieve",
            "result": {"status": "committed"},
        }

        with (
            mock.patch.object(
                self.service,
                "_continue_agent_capability_after_approval",
                return_value=completed,
            ),
            mock.patch.object(
                self.service,
                "_check_agent_capability_job",
                return_value={
                    **completed,
                    "request_id": "request-paperclip-job",
                },
            ),
        ):
            result = self.service.approve_and_continue_capability(
                investigation_id,
                {"request_id": "request-paperclip"},
            )
            checked = self.service.check_capability_request(
                investigation_id,
                {"request_id": "request-paperclip-job"},
            )

        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["execution_owner"], "underlying_agent")
        self.assertEqual(checked["status"], "completed")
        self.assertEqual(checked["execution_owner"], "underlying_agent")
        events = self.service.replay_investigation_events(investigation_id)["events"]
        transition = events[-1]
        self.assertEqual(transition["event_type"], "request_state_changed")
        self.assertEqual(
            transition["payload"]["request_id"], "request-paperclip-job"
        )
        self.assertEqual(transition["payload"]["status"], "completed")
