from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from genomi.interfaces import portal, portal_assets, portal_genomilab, portal_store
from genomi.runtime import context as runtime_context


class _FakeGenomiLabService:
    def bootstrap_workspace(self) -> dict[str, object]:
        return {"status": "ready"}

    def molecular_profile(self) -> dict[str, object]:
        return {"observations": [], "source_artifacts": [], "specimens": [], "assays": []}

    def integrations(self) -> dict[str, object]:
        return {"integrations": [{"provider": "paperclip", "credential_state": "missing"}]}

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
                    {
                        "specialist_assignment_id": "assignment-a",
                        "specialist_role": "rare_disease_specialist",
                        "state": "completed",
                    }
                ],
                "specialist_analyses": [
                    {
                        "specialist_assignment_id": "assignment-a",
                        "general_analysis": {
                            "conclusion": "Review immune and treatment explanations in parallel."
                        },
                        "gaps": ["Medication dates remain unknown."],
                    }
                ],
                "information_gap_versions": [
                    {
                        "logical_information_gap_id": "gap-a",
                        "information_gap_version_id": "gap-a-v1",
                        "version": 1,
                        "status": "open",
                        "statement": "Medication dates remain unknown.",
                    },
                    {
                        "logical_information_gap_id": "gap-b",
                        "information_gap_version_id": "gap-b-v1",
                        "version": 1,
                        "status": "resolved",
                        "statement": "The source report was recovered.",
                    },
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
        self.assertEqual(
            board["specialist_workstreams"][0]["finding"],
            "Review immune and treatment explanations in parallel.",
        )
        self.assertEqual(board["gap_count"], 1)
        self.assertEqual(
            [item["logical_information_gap_id"] for item in board["information_gaps"]],
            ["gap-a", "gap-b"],
        )
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
            with application._current_user() as user_id:
                original = application.store.add_profile_observation(user_id, {
                    "modality": "phenotype",
                    "label": "Recurrent synthetic episodes",
                    "original_wording": "The synthetic episodes keep happening",
                    "source_class": "model_extracted",
                    "verification_state": "unreviewed",
                    "assertion_author": "model",
                })
                latest = application.store.add_profile_observation(user_id, {
                    "modality": "phenotype",
                    "label": "Repeated synthetic episode",
                    "original_wording": "I continue to experience the synthetic event",
                    "source_class": "model_extracted",
                    "verification_state": "unreviewed",
                    "assertion_author": "model",
                })
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

    def test_chat_request_route_remains_the_portal_lab_entrypoint(self) -> None:
        project_request = f"/api/projects/{self.project_id}/request"
        self.assertTrue(portal.is_portal_post_path(project_request))

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
        self.assertIn("Active genome", intake)
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

    def test_chat_composer_accepts_records_beside_natural_language_request(self) -> None:
        html = portal_assets._portal_html("test-csrf-token")
        composer = html.split('<form id="composer"', 1)[1].split("</form>", 1)[0]

        self.assertIn('for="chat-file-attachment"', composer)
        self.assertIn('id="chat-file-attachment"', composer)
        self.assertIn("Attach records", composer)
        self.assertIn('id="prompt"', composer)
        self.assertIn('id="send"', composer)

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
            getProjectId: () => 'project-1',
            getFrameId: () => 'frame-1'
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

    def test_rounds_report_what_each_cycle_changed_and_why(self) -> None:
        # The illustration's arc: medication-only is rejected once the
        # chronology lands, and the CTLA4 branch strengthens in the same round.
        investigation = {
            "cycles": [
                {"cycle_id": "cycle-1", "ordinal": 1, "purpose": "First review"},
                {"cycle_id": "cycle-2", "ordinal": 2, "purpose": "Weigh the chronology"},
            ],
            "hypothesis_versions": [
                {
                    "logical_hypothesis_id": "h-med",
                    "cycle_id": "cycle-1",
                    "version": 1,
                    "statement": "Medication explains the infections.",
                    "status": "open",
                    "revision_rationale": "Raised as the explanation to beat.",
                    "created_at": "2026-08-01T00:00:00Z",
                },
                {
                    "logical_hypothesis_id": "h-med",
                    "cycle_id": "cycle-2",
                    "version": 2,
                    "statement": "Medication explains the infections.",
                    "status": "rejected",
                    "revision_rationale": "The low immunoglobulins predate every drug.",
                    "created_at": "2026-08-02T00:00:00Z",
                },
                {
                    "logical_hypothesis_id": "h-ctla4",
                    "cycle_id": "cycle-2",
                    "version": 1,
                    "statement": "A CTLA4-pathway defect connects the findings.",
                    "status": "strengthened",
                    "revision_rationale": "The functional assay was reduced twice.",
                    "created_at": "2026-08-03T00:00:00Z",
                },
            ],
        }

        rounds = portal_genomilab._investigation_rounds(investigation)

        self.assertEqual([item["ordinal"] for item in rounds], [1, 2])
        self.assertEqual(rounds[0]["purpose"], "First review")
        self.assertEqual(
            rounds[0]["changes"],
            [
                {
                    "statement": "Medication explains the infections.",
                    "status": "open",
                    "from_status": "",
                    "rationale": "Raised as the explanation to beat.",
                }
            ],
        )
        second = rounds[1]["changes"]
        self.assertEqual(
            [(item["from_status"], item["status"]) for item in second],
            [("open", "rejected"), ("", "strengthened")],
        )
        self.assertEqual(
            second[0]["rationale"], "The low immunoglobulins predate every drug."
        )

    def test_a_restated_hypothesis_is_not_reported_as_a_change(self) -> None:
        investigation = {
            "cycles": [{"cycle_id": "cycle-1", "ordinal": 1, "purpose": "Review"}],
            "hypothesis_versions": [
                {
                    "logical_hypothesis_id": "h-1",
                    "cycle_id": "cycle-1",
                    "version": 1,
                    "statement": "An immune-dysregulation disorder connects these.",
                    "status": "open",
                    "revision_rationale": "Raised.",
                },
                {
                    "logical_hypothesis_id": "h-1",
                    "cycle_id": "cycle-1",
                    "version": 2,
                    "statement": "An immune-dysregulation disorder connects these.",
                    "status": "open",
                    "revision_rationale": "Wording clarified.",
                },
            ],
        }

        rounds = portal_genomilab._investigation_rounds(investigation)

        self.assertEqual(len(rounds), 1)
        self.assertEqual(len(rounds[0]["changes"]), 1)

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
            question: 'Could these findings share an explanation?',
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
              {{ logical_hypothesis_id: 'logical-a', statement: 'A shared mechanism is possible.', status: 'strengthened', revision_rationale: 'Two observations now align.' }},
              {{ logical_hypothesis_id: 'logical-b', statement: 'An independent explanation remains open.', status: 'weakened' }}
            ],
            information_gaps: [{{
              logical_information_gap_id: 'logical-gap',
              statement: 'Medication timing is not documented.',
              status: 'open'
            }}],
            evidence_records: [{{
              evidence_record_id: 'evidence-a',
              source_family: 'biomedical_literature',
              evidence: {{ records: [{{ title: 'Public source', pmid: '12345' }}] }}
            }}],
            specialist_workstreams: [
              {{ specialist_role: 'rare_disease_specialist', state: 'completed', finding: 'The pattern warrants parallel review.', gaps: ['Original report'] }},
              {{ specialist_role: 'medication_safety_specialist', state: 'spawned' }}
            ]
          }};
          process.stdout.write(JSON.stringify({{
            workstreams: module.specialistWorkstreamModels(investigation.specialist_workstreams),
            hypotheses: module.hypothesisModels(investigation.hypotheses),
            gaps: module.informationGapModels(investigation.information_gaps),
            brief: module.doctorBriefModel(investigation),
            markdown: module.doctorBriefMarkdown(module.doctorBriefModel(investigation)),
            briefStatus: module.investigationStatusModel(investigation),
            frameScope: [
              Boolean(module.investigationForFrame({{ binding: {{ frame_id: 'frame-a' }}, investigation }}, 'frame-a')),
              Boolean(module.investigationForFrame({{ binding: {{ frame_id: 'frame-a' }}, investigation }}, 'frame-b'))
            ],
            statuses: [
              module.investigationStatusModel('running'),
              module.investigationStatusModel('needs_input'),
              module.investigationStatusModel('failed'),
              module.investigationStatusModel('completed')
            ]
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
                {
                    "role": "Rare disease",
                    "status": "Findings added",
                    "finding": "The pattern warrants parallel review.",
                    "gaps": ["Original report"],
                },
                {
                    "role": "Medication safety",
                    "status": "Researching",
                    "finding": "",
                    "gaps": [],
                },
            ],
        )
        self.assertEqual(state["hypotheses"][0]["statusLabel"], "More supported")
        self.assertEqual(state["hypotheses"][1]["statusLabel"], "Less supported")
        self.assertEqual(state["gaps"][0]["statusLabel"], "Open")
        self.assertEqual(state["frameScope"], [True, False])
        self.assertEqual(
            state["briefStatus"],
            {"label": "Doctor brief ready", "kind": "success"},
        )
        brief = state["brief"]
        self.assertEqual(brief["version"], 3)
        self.assertEqual(brief["hypotheses"], ["A shared mechanism is possible."])
        self.assertEqual(brief["gaps"], ["Medication timing is not documented."])
        self.assertEqual(brief["question"], "Could these findings share an explanation?")
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
        self.assertIn("# Clinician discussion brief", state["markdown"])
        self.assertIn("## Question investigated", state["markdown"])
        self.assertIn("https://pubmed.ncbi.nlm.nih.gov/12345/", state["markdown"])
        self.assertEqual(
            state["statuses"],
            [
                {"label": "Research in progress", "kind": "active"},
                {"label": "Needs your input", "kind": "warning"},
                {"label": "Investigation needs attention", "kind": "error"},
                {"label": "Doctor brief ready", "kind": "success"},
            ],
        )


if __name__ == "__main__":
    unittest.main()
