from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from genomi.interfaces import portal_assets, portal_genomilab, portal_store
from genomi.runtime import context as runtime_context


class _FakeGenomiLabService:
    def __init__(self) -> None:
        self.calls: list[tuple[object, ...]] = []

    def bootstrap_workspace(self) -> dict[str, object]:
        return {"status": "ready"}

    def molecular_profile(self) -> dict[str, object]:
        return {"observations": [], "source_artifacts": [], "specimens": [], "assays": []}

    def integrations(self) -> dict[str, object]:
        return {"integrations": [{"provider": "paperclip", "credential_state": "missing"}]}

    def add_profile_observation(self, payload: dict[str, object]) -> dict[str, object]:
        self.calls.append(("observation", payload))
        return {"observation_revision_id": "observation-revision-1", **payload}

    def add_source_artifact(self, payload: dict[str, object]) -> dict[str, object]:
        self.calls.append(("source_artifact", payload))
        return {"artifact_id": "artifact-1", **payload}

    def add_specimen(self, payload: dict[str, object]) -> dict[str, object]:
        self.calls.append(("specimen", payload))
        return {"specimen_id": "specimen-1", **payload}

    def add_assay(self, payload: dict[str, object]) -> dict[str, object]:
        self.calls.append(("assay", payload))
        return {"assay_id": "assay-1", **payload}

    def connect_integration(self, provider: str, payload: dict[str, object]) -> dict[str, object]:
        self.calls.append(("connect", provider, payload))
        return {"provider": provider, "connection_state": "configured_unverified"}

    def verify_integration(self, provider: str) -> dict[str, object]:
        self.calls.append(("verify", provider))
        return {"provider": provider, "connection_state": "ready"}

    def disconnect_integration(self, provider: str, *, confirmed: bool) -> dict[str, object]:
        self.calls.append(("disconnect", provider, confirmed))
        return {"provider": provider, "connection_state": "not_configured"}


class PortalGenomiLabTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.project = portal_store.create_project(name="Patient workspace", root=self.root)
        self.project_id = str(self.project["project_id"])
        self.service = _FakeGenomiLabService()
        self.events = mock.patch("genomi.interfaces.portal_genomilab.portal_project_events.emit_project_event")
        self.events.start()
        portal_genomilab._SERVICES.clear()

    def tearDown(self) -> None:
        portal_genomilab._SERVICES.clear()
        self.events.stop()
        self.temporary.cleanup()

    def test_profile_and_integrations_are_project_scoped_projections(self) -> None:
        profile = portal_genomilab.project_profile(
            self.project_id, service=self.service, root=self.root
        )
        integrations = portal_genomilab.project_integrations(
            self.project_id, service=self.service, root=self.root
        )

        self.assertEqual(profile["status"], "ready")
        self.assertEqual(profile["profile"]["observations"], [])
        self.assertEqual(integrations["integrations"][0]["provider"], "paperclip")

    def test_board_projects_latest_logical_hypotheses_and_brief(self) -> None:
        service = mock.Mock()
        service.bootstrap_workspace.return_value = {"status": "ready"}
        service.list_investigations.return_value = [
            {
                "investigation": {
                    "investigation_id": "investigation-a",
                    "question": "Could these synthetic findings share an explanation?",
                    "status": "running",
                },
                "hypothesis_versions": [
                    {
                        "logical_hypothesis_id": "logical-a",
                        "hypothesis_version_id": "version-a2",
                        "version": 2,
                        "statement": "Revised explanation A",
                    },
                    {
                        "logical_hypothesis_id": "logical-b",
                        "hypothesis_version_id": "version-b1",
                        "version": 1,
                        "statement": "Current explanation B",
                    },
                    {
                        "logical_hypothesis_id": "logical-a",
                        "hypothesis_version_id": "version-a1",
                        "version": 1,
                        "statement": "Initial explanation A",
                    },
                ],
                "brief_versions": [
                    {
                        "version": 2,
                        "brief": {
                            "title": "Clinician discussion brief",
                            "summary": "Current brief",
                            "claims": [
                                {
                                    "statement": "The reported pattern merits clinical review.",
                                    "evidence_record_ids": ["evidence-a"],
                                    "profile_revision_ids": ["profile-a"],
                                }
                            ],
                            "hypothesis_ids": ["logical-a"],
                            "gap_ids": [],
                            "confirmation_needs": ["Review the original laboratory report."],
                            "professional_questions": ["What testing would distinguish the leading explanations?"],
                            "clinical_boundary": "Research support only; this is not a diagnosis or treatment decision.",
                        },
                    },
                    {"version": 1, "brief": {"summary": "Historical brief"}},
                ],
                "specialist_assignments": [
                    {"specialist_role": "rare_disease_specialist", "state": "completed"}
                ],
                "evidence_records": [
                    {
                        "evidence_record_id": "evidence-a",
                        "source_family": "biomedical_literature",
                        "operation": "paperclip.retrieve_document_evidence",
                    }
                ],
                "research_artifacts": [
                    {"research_artifact_id": "artifact-a", "artifact_kind": "evidence_map"}
                ],
            }
        ]

        board = portal_genomilab.project_board(
            self.project_id, service=service, root=self.root
        )["investigation"]

        self.assertEqual(board["hypothesis_count"], 2)
        self.assertEqual(
            {
                item["logical_hypothesis_id"]: item["hypothesis_version_id"]
                for item in board["hypotheses"]
            },
            {"logical-a": "version-a2", "logical-b": "version-b1"},
        )
        self.assertEqual(board["current_brief_version"], 2)
        self.assertEqual(board["current_brief"]["brief"]["summary"], "Current brief")
        self.assertEqual(board["specialist_count"], 1)
        self.assertEqual(board["specialist_workstreams"][0]["state"], "completed")
        self.assertEqual(board["evidence_count"], 1)
        self.assertEqual(board["research_artifact_count"], 1)
        self.assertEqual(
            board["current_brief"]["brief"]["professional_questions"],
            ["What testing would distinguish the leading explanations?"],
        )

    def test_board_respects_explicit_empty_current_projections(self) -> None:
        board = portal_genomilab._board_investigation(
            {
                "investigation_id": "investigation-a",
                "current_hypotheses": [],
                "hypothesis_versions": [
                    {
                        "logical_hypothesis_id": "logical-a",
                        "version": 1,
                        "statement": "Stale explanation",
                    }
                ],
                "current_brief_version": None,
                "brief_versions": [
                    {"version": 1, "brief": {"summary": "Stale brief"}}
                ],
            }
        )

        self.assertEqual(board["hypotheses"], [])
        self.assertEqual(board["hypothesis_count"], 0)
        self.assertIsNone(board["current_brief_version"])
        self.assertIsNone(board["current_brief"])

    def test_profile_api_projects_canonical_current_facts_and_keeps_history(
        self,
    ) -> None:
        context = {"active_user_id": "user-a", "active_agi_id": None}
        environment = {
            "GENOMI_HOME": str(self.root / "genomi-home"),
            "GENOMI_CONTEXT": "",
            "GENOMI_SESSION_ID": "portal-profile-projection-test",
            **{name: "" for name in runtime_context.AGENT_SESSION_ENVS},
        }
        with mock.patch.dict(os.environ, environment):
            application = portal_genomilab._PortalGenomiLabApplication(
                session_id="portal-profile-projection-test",
                context_provider=lambda: context,
            )
            application.bootstrap_workspace()
            original = application.add_profile_observation(
                {
                    "modality": "phenotype",
                    "label": "Recurrent synthetic episodes",
                    "original_wording": "The synthetic episodes keep happening",
                    "source_class": "model_extracted",
                    "verification_state": "unreviewed",
                    "assertion_author": "model",
                }
            )
            latest = application.add_profile_observation(
                {
                    "modality": "phenotype",
                    "label": "Repeated synthetic episode",
                    "original_wording": "I continue to experience the synthetic event",
                    "source_class": "model_extracted",
                    "verification_state": "unreviewed",
                    "assertion_author": "model",
                }
            )
            projected = portal_genomilab.project_profile(
                self.project_id,
                service=application,
                root=self.root,
            )["profile"]

        self.assertEqual(len(projected["observations"]), 1)
        self.assertEqual(
            projected["observations"][0]["observation_revision_id"],
            latest["observation_revision_id"],
        )
        self.assertEqual(len(projected["observation_history"]), 2)
        self.assertEqual(
            {
                item["observation_revision_id"]
                for item in projected["observation_history"]
            },
            {
                original["observation_revision_id"],
                latest["observation_revision_id"],
            },
        )

    def test_health_and_testing_entities_delegate_to_genomilab_service(self) -> None:
        portal_genomilab.add_profile_observation(
            self.project_id,
            {"modality": "condition", "label": "Condition A", "assertion_status": "present"},
            service=self.service,
            root=self.root,
        )
        portal_genomilab.add_profile_source_artifact(
            self.project_id,
            {"content_sha256": "a" * 64, "source_type": "issued_report", "title": "Report"},
            service=self.service,
            root=self.root,
        )
        portal_genomilab.add_profile_specimen(
            self.project_id,
            {"specimen_type": "blood", "tumor_normal_role": "normal"},
            service=self.service,
            root=self.root,
        )
        portal_genomilab.add_profile_assay(
            self.project_id,
            {
                "assay_type": "panel",
                "assay_scope": {"reported_description": "20 genes"},
                "detection_limits": {"reported_description": "SNVs and small indels"},
            },
            service=self.service,
            root=self.root,
        )

        self.assertEqual([call[0] for call in self.service.calls], ["observation", "source_artifact", "specimen", "assay"])

    def test_provider_actions_preserve_connection_only_contract(self) -> None:
        connected = portal_genomilab.change_integration(
            self.project_id,
            "biohub-esm",
            "connect",
            {"api_token": "secret"},
            service=self.service,
            root=self.root,
        )
        checked = portal_genomilab.change_integration(
            self.project_id,
            "biohub-esm",
            "verify",
            {},
            service=self.service,
            root=self.root,
        )
        disconnected = portal_genomilab.change_integration(
            self.project_id,
            "biohub-esm",
            "disconnect",
            {"confirmed": True},
            service=self.service,
            root=self.root,
        )

        self.assertEqual(connected["integration"]["connection_state"], "configured_unverified")
        self.assertEqual(checked["integration"]["connection_state"], "ready")
        self.assertEqual(disconnected["integration"]["connection_state"], "not_configured")
        self.assertNotIn("secret", repr((connected, checked, disconnected)))

    def test_disconnect_requires_explicit_confirmation(self) -> None:
        with self.assertRaisesRegex(
            portal_genomilab.PortalGenomiLabError, "explicit confirmation"
        ):
            portal_genomilab.change_integration(
                self.project_id,
                "proto",
                "disconnect",
                {},
                service=self.service,
                root=self.root,
            )

    def test_project_services_resolve_only_their_bound_genomi_user(self) -> None:
        second = portal_store.create_project(name="Second patient", root=self.root)
        second_id = str(second["project_id"])
        portal_store.bind_project_genome(
            self.project_id, agi_id="agi-a", user_id="user-a", root=self.root
        )
        portal_store.bind_project_genome(
            second_id, agi_id="agi-b", user_id="user-b", root=self.root
        )
        applications = [mock.Mock(), mock.Mock()]

        with mock.patch(
            "genomi.interfaces.portal_genomilab._PortalGenomiLabApplication",
            side_effect=applications,
        ) as constructor:
            first_service = portal_genomilab._application_service(
                self.project_id, root=self.root
            )
            second_service = portal_genomilab._application_service(
                second_id, root=self.root
            )

        self.assertIs(first_service, applications[0])
        self.assertIs(second_service, applications[1])
        first_context = constructor.call_args_list[0].kwargs["context_provider"]()
        second_context = constructor.call_args_list[1].kwargs["context_provider"]()
        self.assertEqual(first_context["active_user_id"], "user-a")
        self.assertEqual(first_context["active_agi_id"], "agi-a")
        self.assertEqual(second_context["active_user_id"], "user-b")
        self.assertEqual(second_context["active_agi_id"], "agi-b")

    def test_onboarding_has_only_active_genome_selection_and_natural_chat(self) -> None:
        html = portal_assets._portal_html("test-csrf-token")
        templates = Path(__file__).resolve().parents[1] / "src/genomi/interfaces/templates"
        script_path = templates / "portal_genomilab.js"
        script = script_path.read_text()
        api_script = (templates / "portal_api.js").read_text()
        intake = html.split('<section class="genomilab-intake"', 1)[1].split(
            "</section>", 1
        )[0]

        self.assertEqual(intake.count("<button"), 1)
        self.assertIn('data-nav-target="genome-index"', intake)
        self.assertIn("Active Genome Index", intake)
        self.assertIn("Ask in your own words", intake)
        self.assertIn("Genomi will organize the details", intake)
        self.assertIn("Tell Genomi naturally", html)
        self.assertNotIn("data-genomilab-open", html)
        self.assertNotIn('id="patient-context-pane"', html)
        self.assertNotIn('id="research-connections-pane"', html)
        for form_id in (
            "patient-observation-form",
            "patient-report-form",
            "patient-specimen-form",
            "patient-assay-form",
        ):
            self.assertNotIn(form_id, html)
        self.assertIn("await loadBoard();", script)
        self.assertNotIn("loadGenomiLabProfile", script)
        self.assertNotIn("loadGenomiLabIntegrations", script)
        self.assertNotIn("addGenomiLabObservation", api_script)
        self.assertNotIn("changeGenomiLabIntegration", api_script)

    def test_completed_lab_tool_result_triggers_projection_refresh_contract(self) -> None:
        script_path = (
            Path(__file__).resolve().parents[1]
            / "src/genomi/interfaces/templates/portal_genomilab.js"
        )
        node_script = f"""
          const module = await import({script_path.as_uri()!r});
          globalThis.document = {{ getElementById: () => null }};
          let boardLoads = 0;
          const controller = module.createGenomiLabController({{
            api: {{
              loadGenomiLabBoard: async () => {{ boardLoads += 1; return {{}}; }}
            }},
            getProjectId: () => 'project-1'
          }});
          const completedLab = module.completedLabOperation({{
            call: {{ name: 'genomi.genomi.invoke', input: {{ tool: 'lab.update_health_profile' }} }},
            result: {{ isError: false }}
          }});
          const pendingLab = module.completedLabOperation({{
            call: {{ name: 'genomi.genomi.invoke', input: {{ tool: 'lab.update_health_profile' }} }}
          }});
          const publicEvidence = module.completedLabOperation({{
            call: {{ name: 'genomi.genomi.invoke', input: {{ tool: 'paperclip.search_biomedical' }} }},
            result: {{ isError: false }}
          }});
          const refreshed = await controller.refreshFromToolRecord({{
            call: {{ name: 'genomi.genomi.invoke', input: {{ tool: 'lab.update_health_profile' }} }},
            result: {{ isError: false }}
          }});
          const ignored = await controller.refreshFromToolRecord({{
            call: {{ name: 'genomi.genomi.invoke', input: {{ tool: 'paperclip.search_biomedical' }} }},
            result: {{ isError: false }}
          }});
          process.stdout.write(JSON.stringify({{ completedLab, pendingLab, publicEvidence, refreshed, ignored, boardLoads }}));
        """
        completed = subprocess.run(
            ["node", "--input-type=module", "-e", node_script],
            check=True,
            capture_output=True,
            text=True,
        )
        state = json.loads(completed.stdout)

        self.assertEqual(state["completedLab"], "lab.update_health_profile")
        self.assertEqual(state["pendingLab"], "")
        self.assertEqual(state["publicEvidence"], "")
        self.assertTrue(state["refreshed"])
        self.assertFalse(state["ignored"])
        self.assertEqual(state["boardLoads"], 1)

    def test_board_models_render_durable_workstreams_and_complete_brief(self) -> None:
        if shutil.which("node") is None:
            self.skipTest("node is required for the frontend board model check")
        script_path = (
            Path(__file__).resolve().parents[1]
            / "src/genomi/interfaces/templates/portal_genomilab.js"
        )
        node_script = f"""
          const module = await import({script_path.as_uri()!r});
          const investigation = {{
            current_brief_version: 3,
            current_brief: {{
              version: 3,
              brief: {{
                title: 'Clinician discussion brief',
                summary: 'A shared explanation remains possible but unconfirmed.',
                claims: [{{
                  statement: 'One public report supports further review.',
                  evidence_record_ids: ['evidence-a'],
                  profile_revision_ids: ['profile-a']
                }}],
                hypothesis_ids: ['logical-a'],
                gap_ids: ['logical-gap'],
                confirmation_needs: ['Confirm the historical laboratory result.'],
                professional_questions: ['Which test would best distinguish the alternatives?'],
                clinical_boundary: 'Research support only; this is not a diagnosis or treatment decision.'
              }}
            }},
            hypotheses: [
              {{ logical_hypothesis_id: 'logical-a', statement: 'A shared mechanism is possible.' }},
              {{ logical_hypothesis_id: 'logical-gap', statement: 'An independent explanation remains open.', unresolved_gaps: ['Medication timing is not documented.'] }}
            ],
            evidence_records: [{{
              evidence_record_id: 'evidence-a',
              source_family: 'biomedical_literature',
              evidence: {{ records: [{{ title: 'Public source', pmid: '12345' }}] }}
            }}],
            specialist_workstreams: [
              {{ specialist_role: 'rare_disease_specialist', state: 'completed' }},
              {{ specialist_role: 'medication_safety_specialist', state: 'spawned' }}
            ]
          }};
          process.stdout.write(JSON.stringify({{
            workstreams: module.specialistWorkstreamModels(investigation.specialist_workstreams),
            brief: module.doctorBriefModel(investigation)
          }}));
        """
        completed = subprocess.run(
            ["node", "--input-type=module", "-e", node_script],
            check=True,
            capture_output=True,
            text=True,
        )
        state = json.loads(completed.stdout)
        self.assertEqual(
            state["workstreams"],
            [
                {"role": "Rare disease", "status": "Findings added"},
                {"role": "Medication safety", "status": "Researching"},
            ],
        )
        brief = state["brief"]
        self.assertEqual(brief["version"], 3)
        self.assertEqual(brief["hypotheses"], ["A shared mechanism is possible."])
        self.assertEqual(brief["gaps"], ["Medication timing is not documented."])
        self.assertEqual(brief["claims"][0]["profileCount"], 1)
        self.assertEqual(
            brief["claims"][0]["evidence"][0]["url"],
            "https://pubmed.ncbi.nlm.nih.gov/12345/",
        )
        self.assertEqual(
            brief["professionalQuestions"],
            ["Which test would best distinguish the alternatives?"],
        )
        self.assertIn("not a diagnosis", brief["clinicalBoundary"])


if __name__ == "__main__":
    unittest.main()
